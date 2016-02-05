import sys
import sqlite3
import logging
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)
from mpi4py import MPI

# DEBUGGING
import sys
import logging
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)


def getPaths(parents, dict):
    """Returns a list of paths which go from an id in parents to either start or end."""
    # Create a list to the hold the paths from the child of parents to either start or end
    paths = []

    # Loop through each parent
    for parent in parents:
        # If the parent is -1 (i.e. id is either start or end), return an empty path
        if (parent == -1):
            return [[]]

        # Otherwise, recursively get the paths of parent's parents and append them to paths
        else:
            current_paths = getPaths(dict[parent], dict)
            for current_path in current_paths:
                new_path = list(current_path)
                new_path.append(parent)
                paths.append(new_path)

    # Return the list of paths
    return paths


def breadthFirstSearch(start, end, links_forward_db, links_backward_db, verbose):
    """Runs a bi-directional breadth-first search from start to end and returns a list of the shortest paths between them."""
    # If start and end are identical, return the trivial path
    if (start == end):
        return([[start]])
    
    # Create a list to hold every valid path from start to end
    paths = []

    # The unvisited dictionaries are a mapping from page id to a list of that page's parents' ids (initialize them using -1 to signify that start and end have no parents)
    unvisited_forward = {start : [-1]}
    unvisited_backward = {end : [-1]}
    
    # The visited dictionaries are a mappinng from page id to a list of that page's parents' ids (initialize them as empty)
    visited_forward = {}
    visited_backward = {}

    # Create connections to the links databases
    links_forward_conn = sqlite3.connect(links_forward_db)
    lf = links_forward_conn.cursor()
    links_backward_conn = sqlite3.connect(links_backward_db)
    lb = links_backward_conn.cursor()

    # Set the initial forward and backward depths to -1
    forward_depth = -1
    backward_depth = -1

    # Continue the breadth first search until a path has been found or either of the unvisited lists are empty
    while ((len(paths) == 0) and ((len(unvisited_forward) != 0) and (len(unvisited_backward) != 0))):
        #---  FORWARD BREADTH FIRST SEARCH  ---#
        # Run the next iteration of the breadth first search in the forward direction if unvisited forward is smaller than unvisited backward
        if (len(unvisited_forward) <= len(unvisited_backward)):
            # Increment the forward depth
            forward_depth += 1

            # Print out the forward depth if the verbose flag is used
            if (verbose):
                print "Forward depth: " + str(forward_depth)
        
            comm = MPI.COMM_WORLD
            size = comm.Get_size()
            rank = comm.Get_rank()

            logging.debug(str(size))

            if (len(unvisited_forward) != 1):
                start = int((float(rank) / float(size)) * len(unvisited_forward))
                end = int((float(rank + 1) / float(size)) * len(unvisited_forward))
                for i, key in enumerate(unvisited_forward.keys()):
                    if ((i < start) or (i >= end)):
                        del unvisited_forward[key]

            logging.debug(str(unvisited_forward))

            # Add each element from unvisited forward to visited forward
            for id in unvisited_forward:
                visited_forward[id] = unvisited_forward[id]
            
            # Run a query to obtain the ids of the pages which can be reached from the pages whose ids are currently unvisited
            if (len(unvisited_forward) == 1):
                unvisited_forward_keys_tuple = "(" + str(unvisited_forward.keys()[0]) + ")"
            else:
                unvisited_forward_keys_tuple = str(tuple(unvisited_forward.keys()))
            lf.execute("SELECT from_id, to_id FROM links WHERE from_id IN %s" % unvisited_forward_keys_tuple)
        
            # Clear the unvisited forward dictionary
            unvisited_forward.clear()
            
            # Loop through each link retrieved by the query
            for from_id, to_id in lf:
                # If the to id is in neither visited forward nor unvisited forward, add it to unvisited forward
                if ((to_id not in visited_forward) and (to_id not in unvisited_forward)):
                    unvisited_forward[to_id] = [from_id]
            
                # If the to id is in unvisited forward, append the from id as another one of its parents
                elif (to_id in unvisited_forward):
                    unvisited_forward[to_id].append(from_id)
            
            if (rank == 0):
                for i in range(1,size):
                    received_unvisited_forward = comm.recv(source = i, tag = 11)
                    for key, value in received_unvisited_forward:
                        if (key in unvisited_forward):
                            unvisited_forward[key].append(value)
                        else:
                            unvisited_forward[id] = [value]
            else:
                comm.send(unvisited_forward, dest = 0, tag = 11)
        
        #---  BACKWARD BREADTH FIRST SEARCH  ---#
        # Run the next iteration of the breadth first search in the backward direction if unvisited backward is smaller than unvisited forward
        else:
            # Increment the backward depth
            backward_depth += 1

            # Print out the backward depth if the verbose flag is used
            if (verbose):
                print "Backward depth: " + str(backward_depth)
        
            # Add each element from unvisited backward to visited backward
            for id in unvisited_backward:
                visited_backward[id] = unvisited_backward[id]
       
            # Run a query to obtain the ids of the pages which link to the pages whose ids are currently unvisited
            if (len(unvisited_backward) == 1):
                unvisited_backward_keys_tuple = "(" + str(unvisited_backward.keys()[0]) + ")"
            else:
                unvisited_backward_keys_tuple = str(tuple(unvisited_backward.keys()))
            lb.execute("SELECT from_id, to_id FROM links WHERE to_id IN %s" % unvisited_backward_keys_tuple)
        
            # Clear the unvisited backward dictionary
            unvisited_backward.clear()
        
            # Loop through each link retrieved by the query
            for from_id, to_id in lb:
                # If the from id is in neither visited backward nor unvisited backward, add it to unvisited backward
                if ((from_id not in visited_backward) and (from_id not in unvisited_backward)):
                    unvisited_backward[from_id] = [to_id]
            
                # If the from id is in unvisited backward, append the to id as another one of its parents
                elif (from_id in unvisited_backward):
                    unvisited_backward[from_id].append(to_id)
        
        #---  CHECK FOR PATH COMPLETION  ---#
        # If any of the ids in unvisited backward are also in unvisited forward, the breadth first search is complete so find all the valid paths
        for id in unvisited_forward:
            if (id in unvisited_backward):
                # Get the paths from start to id, inclusive
                start_paths = getPaths(unvisited_forward[id], visited_forward)

                # Get the paths from id to end
                end_paths = getPaths(unvisited_backward[id], visited_backward)

                # Concatenate each start path with each end path and add them to the paths list
                for start_path in start_paths:
                    for end_path in end_paths:
                        current_path = list(start_path)
                        current_path.append(id)
                        current_end_path = list(end_path)
                        current_end_path.reverse()
                        current_path.extend(current_end_path)
                        paths.append(current_path)

    # Close the database connections
    lf.close()
    lb.close()

    # Return the list of shortest paths from start to end 
    return paths